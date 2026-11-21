// Standalone checks for smart card data parsing with synthetic input; no card is required.
// c++ -std=c++11 -O2 -Isrc Tests/smartcard_parser_test.cpp \
//     src/Common/CommandAPDU.cpp src/Common/TLVParser.cpp -o /tmp/smartcard_parser_test
#include "Common/CommandAPDU.h"
#include "Common/TLVParser.h"
#include <cstdio>
#include <cstdlib>

using namespace VeraCrypt;

static void Require(bool condition, const char *message)
{
	if (!condition)
	{
		std::fprintf(stderr, "FAIL: %s\n", message);
		std::abort();
	}
}

// Wraps a primitive leaf in `depth` constructed templates (tag 0x70).
static vector<uint8> Nested(size_t depth)
{
	const uint8 leaf[] = { 0x5a, 0x01, 0x42 };
	vector<uint8> encoded(leaf, leaf + sizeof(leaf));
	for (size_t i = 0; i < depth; ++i)
	{
		vector<uint8> outer(1, 0x70);
		const size_t size = encoded.size();
		if (size < 0x80)
			outer.push_back((uint8) size);
		else if (size < 0x100)
		{
			outer.push_back(0x81);
			outer.push_back((uint8) size);
		}
		else
		{
			outer.push_back(0x82);
			outer.push_back((uint8) (size >> 8));
			outer.push_back((uint8) size);
		}
		outer.insert(outer.end(), encoded.begin(), encoded.end());
		encoded.swap(outer);
	}
	return encoded;
}

int main()
{
	{
		vector<uint8> encoded = Nested(8);
		shared_ptr<TLVNode> root = TLVParser::TLV_Parse(encoded.data(), encoded.size());
		shared_ptr<TLVNode> leaf = TLVParser::TLV_Find(root, 0x5a);
		Require(leaf && leaf->Value->size() == 1 && (*leaf->Value)[0] == 0x42, "nested TLV not parsed");
	}
	{
		// A hostile card can nest templates far deeper than any EMV structure.
		// Without a depth limit this recursion exhausts a 1 MB thread stack.
		vector<uint8> encoded = Nested(20000);
		bool rejected = false;
		try { TLVParser::TLV_Parse(encoded.data(), encoded.size()); }
		catch (TLVException &) { rejected = true; }
		Require(rejected, "excessive TLV nesting accepted");
	}
	{
		const uint8 bytes[] = { 0x00, 0xa4, 0x04, 0x00, 0x02, 0x3f, 0x00 };
		CommandAPDU apdu(vector<uint8>(bytes, bytes + sizeof(bytes)));
		Require(apdu.isValid(), "valid case 3 APDU rejected");
		Require(apdu.getAPDU().size() == sizeof(bytes), "parsed APDU cleared after success");
		Require(apdu.getINS() == 0xa4 && apdu.getNc() == 2, "parsed APDU fields");
		vector<uint8> data = apdu.getData();
		Require(data.size() == 2 && data[0] == 0x3f && data[1] == 0x00, "parsed APDU data");
	}
	{
		const uint8 bytes[] = { 0x00, 0xa4 };
		CommandAPDU apdu(vector<uint8>(bytes, bytes + sizeof(bytes)));
		Require(!apdu.isValid() && apdu.getAPDU().empty(), "short APDU accepted");
		Require(apdu.getCLA() == 0 && apdu.getP2() == 0 && apdu.getData().empty(), "invalid APDU getters read out of bounds");
	}
	std::puts("PASS: TLV nesting limit, nested lookup, APDU parse retention and invalid-APDU getters");
	return 0;
}
