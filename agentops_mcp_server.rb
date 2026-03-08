class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/06/22/bd2138f0aaac4cf1b233ad2ff39a4ae6b385b83e12b614214f6dc27ac135/agentops_mcp_server-0.4.10.tar.gz"
  sha256 "241d3191ffe77c3304979a0b410d001333703f300082614c2db5767ea237c979"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
